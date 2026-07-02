from backend.app.services.portfolio_engine import build_wallet_portfolio


from backend.app.core.constants import MIN_SOL_SPENT_FOR_ROI 


def calculate_wallet_roi(db, wallet_address: str):
    portfolio = build_wallet_portfolio(db, wallet_address)

    positions = []

    for position in portfolio["positions"]:
        spent = position["total_sol_spent"]
        received = position["total_sol_received"]

        pnl = received - spent

        if spent >= MIN_SOL_SPENT_FOR_ROI:
            roi = (pnl / spent) * 100
            roi_reliable = True
        else:
            roi = 0
            roi_reliable = False

        positions.append(
            {
                **position,
                "profit_loss_sol": round(pnl, 9),
                "roi_percent": round(roi, 2),
                "roi_reliable": roi_reliable,
                "min_sol_required": MIN_SOL_SPENT_FOR_ROI,
            }
        )

    return {
        "wallet": wallet_address,
        "tokens": len(positions),
        "positions": positions,
    } 