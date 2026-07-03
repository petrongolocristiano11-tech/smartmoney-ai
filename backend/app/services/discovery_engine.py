from backend.app.models.trade import Trade
from backend.app.services.discovered_wallet_service import save_discovered_wallet
from backend.app.services.helius import get_wallet_history
from backend.app.services.wallet_sync_service import sync_wallet


def get_traded_tokens_by_wallet(db, wallet_address: str):
    rows = (
        db.query(Trade.token_mint)
        .filter(Trade.wallet_address == wallet_address)
        .filter(Trade.token_mint.isnot(None))
        .distinct()
        .all()
    )

    tokens = [row[0] for row in rows]

    return {
        "wallet": wallet_address,
        "tokens_found": len(tokens),
        "tokens": tokens,
    }


def get_wallets_by_token(db, token_mint: str):
    rows = (
        db.query(Trade.wallet_address)
        .filter(Trade.token_mint == token_mint)
        .distinct()
        .all()
    )

    wallets = [row[0] for row in rows]

    return {
        "token_mint": token_mint,
        "wallets_found": len(wallets),
        "wallets": wallets,
    }


def discover_wallets_from_token_onchain(token_mint: str):
    transactions = get_wallet_history(token_mint)

    wallets = set()

    for tx in transactions:
        if tx.get("type") != "SWAP":
            continue

        fee_payer = tx.get("feePayer")

        if fee_payer:
            wallets.add(fee_payer)

    return {
        "token_mint": token_mint,
        "wallets_found": len(wallets),
        "wallets": list(wallets),
    }


def discover_import_and_score_wallets_from_token(
    db,
    token_mint: str,
    limit: int = 10,
):
    discovery = discover_wallets_from_token_onchain(token_mint)

    results = []

    for wallet in discovery["wallets"][:limit]:

        score = sync_wallet(db, wallet)

        save_discovered_wallet(
            db=db,
            wallet_address=wallet,
            discovered_from_token=token_mint,
            smart_score=score["smart_score"],
            roi_percent=score["analytics"]["total_roi_percent"],
            win_rate_percent=score["analytics"]["win_rate_percent"],
            profit_loss_sol=score["analytics"]["total_profit_loss_sol"],
            reliable_positions=score["analytics"]["reliable_positions"],
        )

        results.append(
            {
                "wallet": wallet,
                "smart_score": score["smart_score"],
                "roi_percent": score["analytics"]["total_roi_percent"],
                "win_rate_percent": score["analytics"]["win_rate_percent"],
                "profit_loss_sol": score["analytics"]["total_profit_loss_sol"],
                "reliable_positions": score["analytics"]["reliable_positions"],
            }
        )

    results.sort(
        key=lambda item: item["smart_score"],
        reverse=True,
    )

    return {
        "token_mint": token_mint,
        "wallets_discovered": discovery["wallets_found"],
        "wallets_analyzed": len(results),
        "ranking": results,
    }


def discover_full_from_wallet(
    db,
    wallet_address: str,
    max_tokens: int = 5,
    max_wallets_per_token: int = 5,
):
    token_data = get_traded_tokens_by_wallet(db, wallet_address)

    discovered_wallets = set()

    for token in token_data["tokens"][:max_tokens]:
        discovery = discover_wallets_from_token_onchain(token)

        for wallet in discovery["wallets"][:max_wallets_per_token]:
            if wallet != wallet_address:
                discovered_wallets.add(wallet)

    results = []

    for wallet in discovered_wallets:

        score = sync_wallet(db, wallet)

        save_discovered_wallet(
            db=db,
            wallet_address=wallet,
            discovered_from_token="MULTI_TOKEN",
            smart_score=score["smart_score"],
            roi_percent=score["analytics"]["total_roi_percent"],
            win_rate_percent=score["analytics"]["win_rate_percent"],
            profit_loss_sol=score["analytics"]["total_profit_loss_sol"],
            reliable_positions=score["analytics"]["reliable_positions"],
        )

        results.append(
            {
                "wallet": wallet,
                "smart_score": score["smart_score"],
            }
        )

    results.sort(
        key=lambda item: item["smart_score"],
        reverse=True,
    )

    return {
        "seed_wallet": wallet_address,
        "tokens_processed": min(
            max_tokens,
            token_data["tokens_found"],
        ),
        "wallets_discovered": len(discovered_wallets),
        "ranking": results,
    } 