from backend.app.models.trade import Trade
from backend.app.services.smart_score_engine import calculate_smart_score


def get_ranked_wallets(db):
    wallet_rows = (
        db.query(Trade.wallet_address)
        .distinct()
        .all()
    )

    ranking = []

    for row in wallet_rows:
        wallet_address = row[0]

        score_data = calculate_smart_score(db, wallet_address)

        ranking.append(
            {
                "wallet": wallet_address,
                "smart_score": score_data["smart_score"],
                "roi_percent": score_data["analytics"]["total_roi_percent"],
                "win_rate_percent": score_data["analytics"]["win_rate_percent"],
                "profit_loss_sol": score_data["analytics"]["total_profit_loss_sol"],
                "reliable_positions": score_data["analytics"]["reliable_positions"],
            }
        )

    ranking.sort(
        key=lambda wallet: wallet["smart_score"],
        reverse=True,
    )

    return {
        "wallets_found": len(ranking),
        "ranking": ranking,
    } 