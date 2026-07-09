from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.services.smart_score_engine import calculate_smart_score


def get_ranked_wallets(db, limit: int = 100):
    wallets = db.query(DiscoveredWallet).all()

    ranking = []

    for wallet in wallets:
        score_data = calculate_smart_score(
            db,
            wallet.wallet_address,
        )

        ranking.append(
            {
                "wallet": wallet.wallet_address,
                "smart_score": score_data["smart_score"],
                "version": score_data["version"],
                "classification": score_data["dna"]["classification"],
                "traits": score_data["dna"]["traits"],
                "roi_percent": wallet.roi_percent,
                "win_rate_percent": wallet.win_rate_percent,
                "profit_loss_sol": wallet.profit_loss_sol,
            }
        )

    ranking.sort(
        key=lambda item: item["smart_score"],
        reverse=True,
    )

    return {
        "count": len(ranking[:limit]),
        "ranking": ranking[:limit],
    } 