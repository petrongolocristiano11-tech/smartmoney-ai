from backend.app.models.trade import Trade
from backend.app.models.discovered_wallet import DiscoveredWallet


def build_wallet_network(db, wallet_address: str, limit: int = 20):
    token_rows = (
        db.query(Trade.token_mint)
        .filter(Trade.wallet_address == wallet_address)
        .filter(Trade.token_mint.isnot(None))
        .distinct()
        .all()
    )

    tokens = [row[0] for row in token_rows]

    if not tokens:
        return {
            "wallet": wallet_address,
            "tokens_found": 0,
            "connected_wallets": [],
        }

    wallet_rows = (
        db.query(
            Trade.wallet_address,
            Trade.token_mint,
        )
        .filter(Trade.token_mint.in_(tokens))
        .filter(Trade.wallet_address != wallet_address)
        .all()
    )

    network = {}

    for other_wallet, token_mint in wallet_rows:
        if other_wallet not in network:
            network[other_wallet] = set()

        network[other_wallet].add(token_mint)

    results = []

    for other_wallet, shared_tokens in network.items():
        discovered = (
            db.query(DiscoveredWallet)
            .filter(DiscoveredWallet.wallet_address == other_wallet)
            .first()
        )

        smart_score = discovered.smart_score if discovered else 0
        roi_percent = discovered.roi_percent if discovered else 0
        win_rate_percent = discovered.win_rate_percent if discovered else 0

        shared_tokens_count = len(shared_tokens)

        connection_strength = (
            (shared_tokens_count / len(tokens)) * 70
            + (smart_score / 100) * 30
        )

        results.append(
            {
                "wallet": other_wallet,
                "shared_tokens": shared_tokens_count,
                "connection_strength": round(connection_strength, 2),
                "smart_score": smart_score,
                "roi_percent": roi_percent,
                "win_rate_percent": win_rate_percent,
            }
        )

    results.sort(
        key=lambda item: (
            item["connection_strength"],
            item["smart_score"],
        ),
        reverse=True,
    )

    return {
        "wallet": wallet_address,
        "tokens_found": len(tokens),
        "connected_wallets": results[:limit],
    } 