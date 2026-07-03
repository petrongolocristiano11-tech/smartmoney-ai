from backend.app.models.trade import Trade
from backend.app.services.helius import get_wallet_history


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