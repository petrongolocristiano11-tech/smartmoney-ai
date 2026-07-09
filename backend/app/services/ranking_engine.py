from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.wallet_profile import WalletProfile
from backend.app.services.profile_engine import (
    build_wallet_profile,
    ensure_wallet_profiles_table,
)


def _profile_to_ranking_item(profile: WalletProfile):
    return {
        "wallet": profile.wallet_address,
        "smart_score": profile.smart_score,
        "version": profile.version,
        "classification": profile.classification or profile.dna or "NORMAL",
        "traits": profile.traits.split(",") if profile.traits else ["NORMAL"],
        "roi_percent": profile.roi,
        "win_rate_percent": profile.win_rate,
        "profit_loss_sol": profile.profit,
    }


def get_ranked_wallets(db, limit: int = 100):
    ensure_wallet_profiles_table(db)

    profiles = db.query(WalletProfile).all()

    if not profiles:
        discovered_wallets = db.query(DiscoveredWallet).all()

        for wallet in discovered_wallets:
            build_wallet_profile(
                db=db,
                wallet_address=wallet.wallet_address,
            )

        profiles = db.query(WalletProfile).all()

    ranking = [_profile_to_ranking_item(profile) for profile in profiles]

    ranking.sort(
        key=lambda item: item["smart_score"] or 0,
        reverse=True,
    )

    return {
        "count": len(ranking[:limit]),
        "ranking": ranking[:limit],
    } 