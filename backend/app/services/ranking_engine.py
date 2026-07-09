from backend.app.models.discovered_wallet import DiscoveredWallet


def get_ranked_wallets(db):
    wallets = (
        db.query(DiscoveredWallet)
        .order_by(DiscoveredWallet.smart_score.desc())
        .all()
    )

    return {
        "count": len(wallets),
        "wallets": wallets,
    } 