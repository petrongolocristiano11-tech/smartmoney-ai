from backend.app.models.trade import Trade
from backend.app.models.discovered_wallet import DiscoveredWallet


def calculate_token_intelligence(db, token_mint: str):

    buys = (
        db.query(Trade)
        .filter(Trade.token_mint == token_mint)
        .filter(Trade.side == "BUY")
        .all()
    )

    wallets = {}

    for trade in buys:

        if trade.wallet_address in wallets:
            continue

        discovered = (
            db.query(DiscoveredWallet)
            .filter(
                DiscoveredWallet.wallet_address == trade.wallet_address
            )
            .first()
        )

        if discovered:

            wallets[trade.wallet_address] = {
                "smart_score": discovered.smart_score,
                "roi": discovered.roi_percent,
                "win_rate": discovered.win_rate_percent,
            }

    if wallets:

        average_score = sum(
            w["smart_score"]
            for w in wallets.values()
        ) / len(wallets)

    else:

        average_score = 0

    token_score = min(
        100,
        average_score * 0.7
        + len(wallets) * 2
    )

    return {

        "token": token_mint,

        "smart_wallets": len(wallets),

        "average_wallet_score": round(
            average_score,
            2,
        ),

        "token_score": round(
            token_score,
            2,
        ),

        "wallets": wallets,
    } 